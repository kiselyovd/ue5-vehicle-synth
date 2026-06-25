#include "SynthCOCOExporter.h"
#include "Misc/Paths.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/FileHelper.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/DateTime.h"

namespace
{
    static const TArray<FString> ExtendedKeypointNames = {
        TEXT("Right_Front_wheel"), TEXT("Left_Front_wheel"),
        TEXT("Right_Back_wheel"), TEXT("Left_Back_wheel"),
        TEXT("Right_Front_HeadLight"), TEXT("Left_Front_HeadLight"),
        TEXT("Right_Back_HeadLight"), TEXT("Left_Back_HeadLight"),
        TEXT("Exhaust"),
        TEXT("Right_Front_Top"), TEXT("Left_Front_Top"),
        TEXT("Right_Back_Top"), TEXT("Left_Back_Top"),
        TEXT("Center"),
        TEXT("Left_Side_Mirror"), TEXT("Right_Side_Mirror"),
        TEXT("Front_Left_Bumper_Corner"), TEXT("Front_Right_Bumper_Corner"),
        TEXT("Rear_Left_Bumper_Corner"), TEXT("Rear_Right_Bumper_Corner"),
        TEXT("Windshield_Bottom_Left"), TEXT("Windshield_Bottom_Right"),
        TEXT("Rear_Window_Bottom_Left"), TEXT("Rear_Window_Bottom_Right"),
    };

    static const TArray<TArray<int32>> ExtendedSkeleton = {
        {0,2},{1,3},{0,1},{2,3},
        {9,11},{10,12},{9,10},{11,12},
        {4,0},{5,1},{6,2},{7,3},
        {4,9},{5,10},{6,11},{7,12},
        {4,5},{6,7},
        {14,15},
        {14,5},{15,4},
        {16,17},{18,19},
        {16,4},{17,5},{18,6},{19,7},
        {20,21},{22,23},
    };
}

FSynthCOCOExporter::FSynthCOCOExporter(const FString& InOutputPath, const FString& InDatasetName)
    : OutputPath(InOutputPath), DatasetName(InDatasetName)
{
}

FSynthCOCOExporter::~FSynthCOCOExporter()
{
    if (bBegun)
    {
        End();
    }
}

void FSynthCOCOExporter::Begin()
{
    Images.Reset();
    Annotations.Reset();
    NextImageId = 1;
    NextAnnotationId = 1;
    bBegun = true;
}

int32 FSynthCOCOExporter::AddImage(const FString& FileName, int32 Width, int32 Height, const TMap<FString, FString>& Metadata)
{
    check(bBegun);
    const int32 ImgId = NextImageId++;
    TSharedPtr<FJsonObject> Img = MakeShared<FJsonObject>();
    Img->SetNumberField(TEXT("id"), ImgId);
    Img->SetStringField(TEXT("file_name"), FileName);
    Img->SetNumberField(TEXT("width"), Width);
    Img->SetNumberField(TEXT("height"), Height);

    TSharedPtr<FJsonObject> Meta = MakeShared<FJsonObject>();
    for (const auto& Pair : Metadata)
    {
        Meta->SetStringField(Pair.Key, Pair.Value);
    }
    Img->SetObjectField(TEXT("metadata"), Meta);

    Images.Add(Img);
    return ImgId;
}

int32 FSynthCOCOExporter::AddAnnotation(int32 ImageId, const FVector4& BBoxXYWH, const TArray<FCapturedKeypoint>& Keypoints, float Area)
{
    check(bBegun);
    check(Keypoints.Num() == 24);

    const int32 AnnId = NextAnnotationId++;
    TSharedPtr<FJsonObject> Ann = MakeShared<FJsonObject>();
    Ann->SetNumberField(TEXT("id"), AnnId);
    Ann->SetNumberField(TEXT("image_id"), ImageId);
    Ann->SetNumberField(TEXT("category_id"), 1);

    TArray<TSharedPtr<FJsonValue>> BBoxArr;
    BBoxArr.Add(MakeShared<FJsonValueNumber>(BBoxXYWH.X));
    BBoxArr.Add(MakeShared<FJsonValueNumber>(BBoxXYWH.Y));
    BBoxArr.Add(MakeShared<FJsonValueNumber>(BBoxXYWH.Z));
    BBoxArr.Add(MakeShared<FJsonValueNumber>(BBoxXYWH.W));
    Ann->SetArrayField(TEXT("bbox"), BBoxArr);
    Ann->SetNumberField(TEXT("area"), Area);
    Ann->SetNumberField(TEXT("iscrowd"), 0);

    TArray<TSharedPtr<FJsonValue>> KArr;
    int32 NumVisible = 0;
    for (const FCapturedKeypoint& K : Keypoints)
    {
        KArr.Add(MakeShared<FJsonValueNumber>(K.ImageX));
        KArr.Add(MakeShared<FJsonValueNumber>(K.ImageY));
        KArr.Add(MakeShared<FJsonValueNumber>(K.Visibility));
        if (K.Visibility > 0) NumVisible++;
    }
    Ann->SetArrayField(TEXT("keypoints"), KArr);
    Ann->SetNumberField(TEXT("num_keypoints"), NumVisible);

    Annotations.Add(Ann);
    return AnnId;
}

void FSynthCOCOExporter::End()
{
    if (!bBegun) return;

    TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();

    TSharedPtr<FJsonObject> Info = MakeShared<FJsonObject>();
    Info->SetStringField(TEXT("description"), FString::Printf(TEXT("UE5 vehicle synthetic keypoints - %s"), *DatasetName));
    Info->SetStringField(TEXT("version"), TEXT("0.1.0"));
    Info->SetNumberField(TEXT("year"), FDateTime::Now().GetYear());
    Info->SetStringField(TEXT("contributor"), TEXT("kiselyovd"));
    Info->SetStringField(TEXT("date_created"), FDateTime::UtcNow().ToIso8601());
    Root->SetObjectField(TEXT("info"), Info);

    TArray<TSharedPtr<FJsonValue>> ImgArr;
    for (auto& I : Images) ImgArr.Add(MakeShared<FJsonValueObject>(I));
    Root->SetArrayField(TEXT("images"), ImgArr);

    TArray<TSharedPtr<FJsonValue>> AnnArr;
    for (auto& A : Annotations) AnnArr.Add(MakeShared<FJsonValueObject>(A));
    Root->SetArrayField(TEXT("annotations"), AnnArr);

    TSharedPtr<FJsonObject> Cat = MakeShared<FJsonObject>();
    Cat->SetNumberField(TEXT("id"), 1);
    Cat->SetStringField(TEXT("name"), TEXT("vehicle"));
    Cat->SetStringField(TEXT("supercategory"), TEXT("vehicle"));
    TArray<TSharedPtr<FJsonValue>> KptNames;
    for (const FString& N : ExtendedKeypointNames) KptNames.Add(MakeShared<FJsonValueString>(N));
    Cat->SetArrayField(TEXT("keypoints"), KptNames);
    TArray<TSharedPtr<FJsonValue>> SkelArr;
    for (const TArray<int32>& E : ExtendedSkeleton)
    {
        TArray<TSharedPtr<FJsonValue>> Edge;
        Edge.Add(MakeShared<FJsonValueNumber>(E[0]));
        Edge.Add(MakeShared<FJsonValueNumber>(E[1]));
        SkelArr.Add(MakeShared<FJsonValueArray>(Edge));
    }
    Cat->SetArrayField(TEXT("skeleton"), SkelArr);
    TArray<TSharedPtr<FJsonValue>> CatArr;
    CatArr.Add(MakeShared<FJsonValueObject>(Cat));
    Root->SetArrayField(TEXT("categories"), CatArr);

    FString Out;
    auto Writer = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);

    IPlatformFile& PF = FPlatformFileManager::Get().GetPlatformFile();
    PF.CreateDirectoryTree(*FPaths::GetPath(OutputPath));
    FFileHelper::SaveStringToFile(Out, *OutputPath);

    bBegun = false;
}
